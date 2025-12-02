import re


def validate_password_strength(password):
    """
    Validate password strength based on security requirements.
    
    Requirements:
    - Minimum 10 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one special character (@$!%*?&)
    - No sequential numbers (e.g., 123, 456, 789)
    
    Args:
        password (str): The password to validate
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not password:
        return False, "Password is required"
    
    # Check minimum length
    if len(password) < 10:
        return False, "Password must be at least 10 characters long"
    
    # Check for uppercase letter
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    # Check for lowercase letter
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    # Check for special character
    if not re.search(r'[@$!%*?&]', password):
        return False, "Password must contain at least one special character (@$!%*?&)"
    
    # Check for sequential numbers (3 or more consecutive digits)
    # This checks for patterns like 123, 234, 345, etc. and 987, 876, 765, etc.
    if has_sequential_numbers(password):
        return False, "Password must not contain sequential numbers (e.g., 123, 456, 789)"
    
    return True, None


def has_sequential_numbers(password):
    """
    Check if password contains sequential numbers (ascending or descending).
    
    Args:
        password (str): The password to check
        
    Returns:
        bool: True if sequential numbers found, False otherwise
    """
    # Extract all digits from password
    digits = ''.join(c for c in password if c.isdigit())
    
    # Check for sequences of 3 or more consecutive digits
    if len(digits) < 3:
        return False
    
    for i in range(len(digits) - 2):
        # Get three consecutive digits
        num1 = int(digits[i])
        num2 = int(digits[i + 1])
        num3 = int(digits[i + 2])
        
        # Check if they form an ascending sequence (e.g., 123, 456)
        if num2 == num1 + 1 and num3 == num2 + 1:
            return True
        
        # Check if they form a descending sequence (e.g., 321, 654)
        if num2 == num1 - 1 and num3 == num2 - 1:
            return True
    
    return False
