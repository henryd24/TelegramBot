import requests
import json

def upload_image(render_image):
    """
    Uploads an image to the picsur.org API and returns the image URL, image ID, and delete key.

    Args:
        render_image: The image to be uploaded.

    Returns:
        A tuple containing the image URL, image ID, and delete key if the upload is successful.
        If the upload fails, returns None for all values.
    """
    try:
        reqUrl = "https://picsur.org/api/image/upload"
        post_files = {
            "image": render_image,
        }
        headersList = {
         "Accept": "application/json" 
        }
        response = requests.request("POST", reqUrl, files=post_files, headers=headersList)
        response_json = response.json()
        if response.status_code == 201 and response_json['success']:
            image_id = response_json['data']['id']
            delete_key = response_json['data']['delete_key']
            image_url = f"https://picsur.org/i/{image_id}.png"
            return image_url, image_id, delete_key
        else:
            return None, None, None
    except Exception as e:
        print(f"Error al cargar la imagen: {str(e)}")
        return None, None, None

def delete_image(image_id, delete_key):
    """
    Deletes an image using the provided image ID and delete key.

    Args:
        image_id (str): The ID of the image to be deleted.
        delete_key (str): The delete key associated with the image.

    Returns:
        bool: True if the image is successfully deleted, False otherwise.
    """
    reqUrl = "https://picsur.org/api/image/delete/key"
    headersList = {
     "Accept": "application/json",
     "Content-Type": "application/json" 
    }
    payload = json.dumps({
        "id": image_id,
        "key": delete_key
    })
    response = requests.request("POST", reqUrl, data=payload,  headers=headersList)
    return response.status_code == 200
