/**
 * Shared password validation logic for ContextForge
 * Used across user creation and password change forms
 */

window.PasswordValidator = {
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
      special: /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>\/?]/.test(password)
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
   * @param {string} password - The password to evaluate
   * @param {object} requirements - Password requirements from backend
   * @returns {object} Object with label (string) and color (string)
   */
  getPasswordStrength: function(password, requirements) {
    let score = 0;

    // Length score (0-2 points)
    if (password.length >= requirements.min_length) {
      score += 2;
    } else if (password.length >= 8) {
      score += 1;
    }

    // Character type scores (1 point each)
    if (/[A-Z]/.test(password)) score++;
    if (/[a-z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[!@#$%^&*()_+\-=[\]{};':"\\|,.<>\/?]/.test(password)) score++;

    // Extra length bonus
    if (password.length >= requirements.min_length + 8) score++;

    if (score <= 3) return { label: 'Weak', color: 'text-red-500' };
    if (score <= 5) return { label: 'Medium', color: 'text-yellow-500' };
    return { label: 'Strong', color: 'text-green-500' };
  }
};
