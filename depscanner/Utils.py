def get_response_emoji(response_code: int):
    """Returns an emoji based on the response code"""
    if response_code == 200:
        return "🟢"
    elif response_code == 404:
        return "🔴"
    elif response_code == 429:
        return "🟣"
    else:
        return "🔵"


def get_stars_score(repo_stars: int = 0):
    """This function represents the stars of a repository with emojis"""
    star_marker = ""
    if repo_stars < 10:
        star_marker = "⭐"
    elif repo_stars < 50:
        star_marker = "⭐⭐"
    elif repo_stars < 500:
        star_marker = "⭐⭐⭐"
    elif repo_stars < 2000:
        star_marker = "⭐⭐⭐⭐"
    elif repo_stars >= 2000:
        star_marker = "⭐⭐⭐⭐⭐"
    return star_marker
