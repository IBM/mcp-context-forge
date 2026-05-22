/**
 * Shared password validation logic for ContextForge
 * Used across user creation and password change forms
 */

window.PasswordValidator = window.PasswordValidator || {
  /**
   * Check password complexity requirements (3 of 4 character types)
   * @param {string} password - The password to validate
   * @param {object} requirements - Password requirements from backend
   * @returns {object} Object with has (character types present), typesPresent (count), met (boolean)
   */
  checkComplexity: function(password, requirements) {
    const has = {
      uppercase: /[A-Z]/.test(password),
      lowercase: /[a-z]/.test(password),
      numbers: /[0-9]/.test(password),
      special: /[!@#$%^&*(),.?":{}|<>\-_=+\[\]\\;'`~]/.test(password)
    };

    const typesPresent = Object.values(has).filter(Boolean).length;
    const complexityRequired = requirements.complexity_required || 3;

    return {
      has,
      typesPresent,
      met: typesPresent >= complexityRequired
    };
  },

  /**
   * Check if password meets minimum length requirement
   * @param {string} password - The password to validate
   * @param {object} requirements - Password requirements from backend
   * @returns {boolean} True if length requirement is met
   */
  checkLength: function(password, requirements) {
    return password.length >= requirements.min_length;
  },

  /**
   * Validate password against all requirements
   * @param {string} password - The password to validate
   * @param {object} requirements - Password requirements from backend
   * @returns {object} Object with isValid (boolean) and details (object)
   */
  validate: function(password, requirements) {
    const lengthMet = this.checkLength(password, requirements);
    const complexity = this.checkComplexity(password, requirements);

    return {
      isValid: lengthMet && complexity.met,
      details: {
        length: lengthMet,
        complexity: complexity.met,
        complexityDetails: complexity.has,
        complexityCount: complexity.typesPresent
      }
    };
  },

  /**
   * Update requirement indicator UI element
   * @param {string} elementId - The ID of the element to update
   * @param {boolean} met - Whether the requirement is met
   */
  updateRequirementUI: function(elementId, met) {
    const element = document.getElementById(elementId);
    if (!element) return;

    const icon = element.querySelector('i');
    if (!icon) return;

    // Reset classes
    icon.className = 'fas mr-2';

    if (met) {
      icon.classList.add('fa-check-circle', 'text-green-600');
      element.classList.remove('text-gray-600');
      element.classList.add('text-green-600');
    } else {
      icon.classList.add('fa-circle', 'text-gray-400');
      element.classList.remove('text-green-600');
      element.classList.add('text-blue-600');
    }
  },

  /**
   * Calculate password strength score
   *
   * Note: This is a simplified client-side approximation for real-time UX feedback.
   * The authoritative strength calculation is performed server-side by
   * PasswordPolicyService.get_password_strength_score() which includes additional
   * checks for common passwords, sequential characters, and entropy analysis.
   *
   * This client-side version provides immediate visual feedback during password entry
   * but final validation and scoring always happens on the backend.
   *
   * @param {string} password - The password to evaluate
   * @param {object} requirements - Password requirements from backend
   * @returns {object} Object with label (string) and color (string)
   */
  getPasswordStrength: function(password, requirements) {
    let score = 0;

    // Length scoring (0-25 points, simplified from backend scale)
    if (password.length >= requirements.min_length) {
      score += 25;
    } else if (password.length >= 8) {
      score += 15;
    }

    // Character type scores (15 points each, max 60)
    const hasLower = /[a-z]/.test(password);
    const hasUpper = /[A-Z]/.test(password);
    const hasDigit = /[0-9]/.test(password);
    const hasSpecial = /[!@#$%^&*(),.?":{}|<>\-_=+\[\]\\;'`~]/.test(password);

    const complexityCount = [hasLower, hasUpper, hasDigit, hasSpecial].filter(Boolean).length;
    score += complexityCount * 15;

    // Extra length bonus (10 points)
    if (password.length >= requirements.min_length + 8) {
      score += 10;
    }

    // Note: Backend also checks for common passwords (-score cap), sequential chars,
    // and entropy, but these are too expensive for real-time client-side validation

    // Map to strength labels (scale: 0-100, simplified from backend thresholds)
    if (score < 50) return { label: 'Weak', color: 'text-red-500' };
    if (score < 70) return { label: 'Medium', color: 'text-yellow-500' };
    return { label: 'Strong', color: 'text-green-500' };
  }
};
