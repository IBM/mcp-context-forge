((Admin) => {
    /* global marked, DOMPurify */
    // Consts
    Admin.MASKED_AUTH_VALUE = "*****";
    /**
    * Header validation constants and functions
    */
    Admin.HEADER_NAME_REGEX = /^[A-Za-z0-9-]+$/;
    Admin.MAX_HEADER_VALUE_LENGTH = 4096;
})(window.Admin)