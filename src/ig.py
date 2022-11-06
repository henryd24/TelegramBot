import requests,re,instaloader

def get_imgvid_instagram(message,L):
    if 'https://www.instagram.com/stories' in message:
        regex_code = re.search("https:\/\/www\.instagram\.com\/(stories)\/.*\/(\d+)", message)
        code = int(regex_code.group(2))
        post = instaloader.StoryItem.from_mediaid(L.context,code)
        photo_url = post.url
        video_url = post.video_url
        return photo_url,video_url
    else:
        regex_code = re.search("https:\/\/www\.instagram\.com\/(p|reel)\/(\w*)", message)
        code = regex_code.group(2)
        post = instaloader.Post.from_shortcode(L.context,code)
        photo_url = post.url
        video_url = post.video_url
        data = requests.get(photo_url).content
        return data,video_url
