import logging,youtube_dl
def get_imgvid_facebook(url):
    try:
        secondCheck = False
        if 'https://m' in url:
            url = url.replace('https://m','https://www')
            secondCheck=True
        ydl = youtube_dl.YoutubeDL({'outtmpl': '%(id)s.%(ext)s','format' : 'bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best', 
                                    'merge-output-format' : 'mp4','postprocessors': [{'key': 'FFmpegVideoConvertor','preferedformat': 'mp4'}]})
        with ydl:
            result = ydl.extract_info(
            url,
            download=False # We just want to extract the info
        )
        if 'entries' in result:
        # Can be a playlist or a list of videos
            video = result['entries'][0]
        else:
        # Just a video
            video = result
        if 'url' not in video:
        # If video is large
            video = [values for values in video['formats'] if values['format_id'] == 'hd'][0]
        video_url = video['url']
        if secondCheck:
            video_url = get_imgvid_facebook(video_url)
        return video_url
    except Exception as e:
        logging.error("Exception ocurred getting url", exc_info=True)