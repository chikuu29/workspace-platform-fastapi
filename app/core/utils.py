def get_device_type(user_agent: str) -> str:
    """Determine if the request is from a mobile or desktop based on the User-Agent."""
    mobile_keywords = ["Mobile", "Android", "iPhone", "iPad"]
    if any(keyword in user_agent for keyword in mobile_keywords):
        return "Mobile"
    return "Desktop"
