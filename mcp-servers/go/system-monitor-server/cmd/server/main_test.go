package main

import (
    "testing"
)

func TestVersionJSON(t *testing.T) {
    version := versionJSON()
    if version == "" {
        t.Error("Version JSON should not be empty")
    }
}

func TestHealthJSON(t *testing.T) {
    health := healthJSON()
    if health == "" {
        t.Error("Health JSON should not be empty")
    }
}
