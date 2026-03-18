package controller

import (
	"bufio"
	"context"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	cfv1 "github.com/IBM/mcp-context-forge/operator/api/v1alpha1"
)

const (
	pluginsVolumeName          = "plugins"
	pluginsMountPath           = "/plugins"
	pluginsConfigVolumeName    = "plugins-config"
	pluginsConfigMountPath     = "/etc/mcpgateway/plugins-config"
	defaultGitImage            = "alpine/git:latest"
	annotationPluginsGitSHA    = "contextforge.io/plugins-git-sha"
)

// resolveGitCommitSHA resolves a git ref (branch/tag) to its commit SHA
// using the Git smart HTTP protocol (/info/refs?service=git-upload-pack).
func resolveGitCommitSHA(ctx context.Context, c client.Client, gs *cfv1.GitSourceSpec, namespace string) (string, error) {
	logger := log.FromContext(ctx)

	repoURL := strings.TrimSuffix(gs.URL, "/")
	if !strings.HasSuffix(repoURL, ".git") {
		repoURL += ".git"
	}
	infoRefsURL := repoURL + "/info/refs?service=git-upload-pack"

	req, err := http.NewRequestWithContext(ctx, "GET", infoRefsURL, nil)
	if err != nil {
		return "", fmt.Errorf("creating request: %w", err)
	}

	// Add auth from secretRef if provided.
	if gs.SecretRef != nil {
		secret := &corev1.Secret{}
		if err := c.Get(ctx, types.NamespacedName{Name: gs.SecretRef.Name, Namespace: namespace}, secret); err != nil {
			return "", fmt.Errorf("reading git credentials secret %q: %w", gs.SecretRef.Name, err)
		}
		if token, ok := secret.Data["token"]; ok {
			req.Header.Set("Authorization", "Bearer "+string(token))
		} else if username, ok := secret.Data["username"]; ok {
			if password, ok := secret.Data["password"]; ok {
				req.SetBasicAuth(string(username), string(password))
			}
		}
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("fetching git refs from %s: %w", infoRefsURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("git info/refs returned HTTP %d", resp.StatusCode)
	}

	ref := gs.Ref
	if ref == "" {
		ref = "main"
	}

	sha, err := findRefInPktLineStream(resp.Body, ref)
	if err != nil {
		return "", fmt.Errorf("parsing git refs for %q: %w", ref, err)
	}

	logger.Info("resolved git ref", "ref", ref, "sha", sha[:12])
	return sha, nil
}

// findRefInPktLineStream parses the Git pkt-line stream and returns the SHA
// for the first ref matching the given name (checked as refs/heads/<ref>,
// refs/tags/<ref>, or an exact match).
func findRefInPktLineStream(r io.Reader, ref string) (string, error) {
	reader := bufio.NewReader(r)
	patterns := []string{
		"refs/heads/" + ref,
		"refs/tags/" + ref,
		ref,
	}

	for {
		// Read 4-byte hex length prefix.
		lenBuf := make([]byte, 4)
		if _, err := io.ReadFull(reader, lenBuf); err != nil {
			if err == io.EOF || err == io.ErrUnexpectedEOF {
				break
			}
			return "", err
		}

		// Decode length (includes the 4 prefix bytes).
		pktLen, err := strconv.ParseInt(string(lenBuf), 16, 32)
		if err != nil {
			return "", fmt.Errorf("invalid pkt-line length %q: %w", string(lenBuf), err)
		}
		if pktLen == 0 {
			continue // flush packet
		}
		if pktLen < 4 {
			return "", fmt.Errorf("invalid pkt-line length %d", pktLen)
		}

		// Read payload.
		dataBuf := make([]byte, pktLen-4)
		if _, err := io.ReadFull(reader, dataBuf); err != nil {
			return "", err
		}

		data := string(dataBuf)

		// Strip capabilities after NUL byte.
		if idx := strings.IndexByte(data, 0); idx >= 0 {
			data = data[:idx]
		}
		data = strings.TrimSpace(data)

		// Skip service advertisement lines.
		if strings.HasPrefix(data, "#") {
			continue
		}

		parts := strings.SplitN(data, " ", 2)
		if len(parts) != 2 {
			continue
		}
		sha, refName := parts[0], parts[1]

		// Validate SHA is hex.
		if len(sha) < 40 {
			continue
		}
		if _, err := hex.DecodeString(sha[:40]); err != nil {
			continue
		}

		for _, pattern := range patterns {
			if refName == pattern {
				return sha[:40], nil
			}
		}
	}

	return "", fmt.Errorf("ref %q not found in repository", ref)
}

// pluginsGitInitContainer returns an initContainer that clones the git repo
// and copies the plugin directory into the shared emptyDir volume.
func pluginsGitInitContainer(gs *cfv1.GitSourceSpec) corev1.Container {
	ref := gs.Ref
	if ref == "" {
		ref = "main"
	}

	// Build the clone + copy script.
	var script string
	if gs.Directory != "" {
		script = fmt.Sprintf(
			`git clone --depth 1 --branch %q %q /tmp/repo && cp -a /tmp/repo/%s/. %s/`,
			ref, gs.URL, gs.Directory, pluginsMountPath,
		)
	} else {
		script = fmt.Sprintf(
			`git clone --depth 1 --branch %q %q /tmp/repo && cp -a /tmp/repo/. %s/`,
			ref, gs.URL, pluginsMountPath,
		)
	}

	container := corev1.Container{
		Name:    "git-clone-plugins",
		Image:   defaultGitImage,
		Command: []string{"sh", "-c", script},
		VolumeMounts: []corev1.VolumeMount{{
			Name:      pluginsVolumeName,
			MountPath: pluginsMountPath,
		}},
		SecurityContext: &corev1.SecurityContext{
			AllowPrivilegeEscalation: boolPtr(false),
		},
	}

	// Inject token for private repos.
	if gs.SecretRef != nil {
		container.Env = []corev1.EnvVar{{
			Name: "GIT_TOKEN",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: gs.SecretRef.Name},
					Key:                  "token",
					Optional:             boolPtr(true),
				},
			},
		}}
		// Rewrite script to use token auth via git credential helper.
		var cloneScript string
		if gs.Directory != "" {
			cloneScript = fmt.Sprintf(
				`if [ -n "$GIT_TOKEN" ]; then
  git -c http.extraHeader="Authorization: Bearer $GIT_TOKEN" clone --depth 1 --branch %q %q /tmp/repo
else
  git clone --depth 1 --branch %q %q /tmp/repo
fi
cp -a /tmp/repo/%s/. %s/`,
				ref, gs.URL, ref, gs.URL, gs.Directory, pluginsMountPath,
			)
		} else {
			cloneScript = fmt.Sprintf(
				`if [ -n "$GIT_TOKEN" ]; then
  git -c http.extraHeader="Authorization: Bearer $GIT_TOKEN" clone --depth 1 --branch %q %q /tmp/repo
else
  git clone --depth 1 --branch %q %q /tmp/repo
fi
cp -a /tmp/repo/. %s/`,
				ref, gs.URL, ref, gs.URL, pluginsMountPath,
			)
		}
		container.Command = []string{"sh", "-c", cloneScript}
	}

	return container
}
