# MediScan Email Templates
# Clean, professional email templates with brand color #60a5fa (blue-400)

def get_verification_email(first_name, verification_code):
    """Modern Clean Email Style - Fully Responsive"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                .code-box {{ padding: 20px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
                .code {{ font-size: 32px !important; letter-spacing: 6px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Welcome, {first_name}!</h2>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">Thank you for joining MediScan. To complete your registration, please verify your email address with the code below:</p>
                                
                                <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px 0;">
                                    <tr>
                                        <td align="center" class="code-box" style="background-color: #eff6ff; border: 2px solid #60a5fa; border-radius: 8px; padding: 24px;">
                                            <p style="margin: 0 0 8px 0; color: #60a5fa; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Verification Code</p>
                                            <h1 class="code" style="margin: 0; color: #2563eb; font-size: 36px; font-weight: 700; letter-spacing: 8px; font-family: 'Courier New', monospace;">{verification_code}</h1>
                                        </td>
                                    </tr>
                                </table>
                                
                                <p style="margin: 0 0 8px 0; color: #6b7280; font-size: 14px; line-height: 1.5;">This code will expire in 15 minutes.</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 14px;">If you didn't create this account, you can safely ignore this email.</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def get_resend_verification_email(first_name, verification_code):
    """Modern Clean Email Style - Fully Responsive"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                .code-box {{ padding: 20px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
                .code {{ font-size: 32px !important; letter-spacing: 6px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Hello, {first_name}!</h2>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">You requested a new verification code for your MediScan account:</p>
                                
                                <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px 0;">
                                    <tr>
                                        <td align="center" class="code-box" style="background-color: #eff6ff; border: 2px solid #60a5fa; border-radius: 8px; padding: 24px;">
                                            <p style="margin: 0 0 8px 0; color: #60a5fa; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Verification Code</p>
                                            <h1 class="code" style="margin: 0; color: #2563eb; font-size: 36px; font-weight: 700; letter-spacing: 8px; font-family: 'Courier New', monospace;">{verification_code}</h1>
                                        </td>
                                    </tr>
                                </table>
                                
                                <p style="margin: 0 0 8px 0; color: #6b7280; font-size: 14px; line-height: 1.5;">This code will expire in 15 minutes.</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 14px;">If you didn't request this code, please ignore this email.</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def get_password_reset_email(first_name, reset_code):
    """Modern Clean Email Style - Fully Responsive (Legacy - with code only)"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                .code-box {{ padding: 20px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
                .code {{ font-size: 32px !important; letter-spacing: 6px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Password Reset Request</h2>
                                <p style="margin: 0 0 8px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">Hello {first_name},</p>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">We received a request to reset your password. Use the code below to proceed:</p>
                                
                                <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px 0;">
                                    <tr>
                                        <td align="center" class="code-box" style="background-color: #eff6ff; border: 2px solid #60a5fa; border-radius: 8px; padding: 24px;">
                                            <p style="margin: 0 0 8px 0; color: #60a5fa; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Reset Code</p>
                                            <h1 class="code" style="margin: 0; color: #2563eb; font-size: 36px; font-weight: 700; letter-spacing: 8px; font-family: 'Courier New', monospace;">{reset_code}</h1>
                                        </td>
                                    </tr>
                                </table>
                                
                                <p style="margin: 0 0 8px 0; color: #6b7280; font-size: 14px; line-height: 1.5;">This code will expire in 15 minutes for your security.</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 14px;">If you didn't request this password reset, please ignore this email. Your account is secure.</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def get_password_reset_email_with_link(first_name, reset_token, reset_code, base_url="http://localhost:8051"):
    """Modern Clean Email Style with One-Click Verification Button"""
    verification_url = f"{base_url}/auth/verify-password-reset/{reset_token}"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                .code-box {{ padding: 20px !important; }}
                .button {{ padding: 14px 28px !important; font-size: 15px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
                .code {{ font-size: 28px !important; letter-spacing: 4px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Password Reset Request</h2>
                                <p style="margin: 0 0 8px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">Hello {first_name},</p>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">We received a request to reset your password. Click the button below to verify and reset your password:</p>
                                
                                <!-- Reset Button -->
                                <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 32px 0;">
                                    <tr>
                                        <td align="center">
                                            <a href="{verification_url}" class="button" style="display: inline-block; background-color: #60a5fa; color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 8px; font-size: 16px; font-weight: 600; box-shadow: 0 4px 6px rgba(96, 165, 250, 0.3);">Reset My Password</a>
                                        </td>
                                    </tr>
                                </table>
                                
                                <!-- Divider -->
                                <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px 0;">
                                    <tr>
                                        <td style="border-top: 1px solid #e5e7eb; padding-top: 24px;">
                                            <p style="margin: 0 0 16px 0; color: #6b7280; font-size: 14px; text-align: center;">Or use this verification code:</p>
                                        </td>
                                    </tr>
                                </table>
                                
                                <!-- Verification Code -->
                                <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px 0;">
                                    <tr>
                                        <td align="center" class="code-box" style="background-color: #eff6ff; border: 2px solid #60a5fa; border-radius: 8px; padding: 20px;">
                                            <p style="margin: 0 0 8px 0; color: #60a5fa; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Verification Code</p>
                                            <h1 class="code" style="margin: 0; color: #2563eb; font-size: 32px; font-weight: 700; letter-spacing: 6px; font-family: 'Courier New', monospace;">{reset_code}</h1>
                                        </td>
                                    </tr>
                                </table>
                                
                                <p style="margin: 0 0 8px 0; color: #6b7280; font-size: 14px; line-height: 1.5;">This link and code will expire in 15 minutes for your security.</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 14px;">If you didn't request this password reset, please ignore this email. Your account is secure.</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def get_password_changed_email(first_name):
    """Modern Clean Email Style - Fully Responsive"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Password Successfully Changed</h2>
                                <p style="margin: 0 0 8px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">Hello {first_name},</p>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">Your MediScan account password has been successfully updated. You can now log in with your new password.</p>
                                
                                <p style="margin: 0; color: #9ca3af; font-size: 14px;">If you did not authorize this change, please contact our support team immediately.</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def get_test_email(body):
    """Modern Clean Email Style - Fully Responsive"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Test Email</h2>
                                <div style="background-color: #f9fafb; border-radius: 8px; border-left: 4px solid #60a5fa; padding: 16px; margin: 20px 0;">
                                    <p style="margin: 0; color: #4b5563; font-size: 15px; line-height: 1.6; white-space: pre-wrap;">{body}</p>
                                </div>
                                <p style="margin: 0; color: #9ca3af; font-size: 14px;">This is a test email from the MediScan API system.</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def get_profile_shared_email(sharer_name, profile_name, recipient_name):
    """Email notification when a profile is shared"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Hello, {{recipient_name}}!</h2>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                    <strong>{{sharer_name}}</strong> has shared a medical profile with you: <strong>{{profile_name}}</strong>.
                                </p>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                    You can now view the medical records and reports associated with this profile in your MediScan app.
                                </p>
                                <div style="text-align: center; margin: 32px 0;">
                                    <a href="#" style="background-color: #60a5fa; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block;">View Profile</a>
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def get_report_uploaded_email(uploader_name, profile_name, report_name, recipient_name):
    """Email notification when a new report is uploaded"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .content {{ padding: 24px 20px !important; }}
                .header {{ padding: 24px 20px !important; }}
                .footer {{ padding: 20px !important; }}
                h1 {{ font-size: 24px !important; }}
                h2 {{ font-size: 20px !important; }}
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px;">
                        <tr>
                            <td class="header" style="background-color: #60a5fa; padding: 32px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">MediScan</h1>
                                <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Where Health Meets Technology</p>
                            </td>
                        </tr>
                        <tr>
                            <td class="content" style="padding: 40px;">
                                <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Hello, {{recipient_name}}!</h2>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                    A new medical report has been added to the profile <strong>{{profile_name}}</strong>.
                                </p>
                                <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                    <strong>Report:</strong> {{report_name}}<br>
                                    <strong>Uploaded by:</strong> {{uploader_name}}
                                </p>
                                <div style="text-align: center; margin: 32px 0;">
                                    <a href="#" style="background-color: #60a5fa; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block;">View Report</a>
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <td class="footer" style="background-color: #f9fafb; padding: 24px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">MediScan Team</p>
                                <p style="margin: 0; color: #9ca3af; font-size: 12px;">&copy; 2025 MediScan. All rights reserved.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
