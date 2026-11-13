from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler


class MaxRequestSizeUploadHandler(FileUploadHandler):
    """Refuse an oversized multipart request before any of its body is read.

    Django streams uploads to a temp file and only the form fields are size-limited, so without this a
    single request could fill the disk before a field validator ever ran. The check uses the declared
    Content-Length, which the web server enforces, so it cannot be bypassed by lying. The request is
    answered with a 400 (Django's own treatment of ``RequestDataTooBig``).
    """

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if content_length and content_length > settings.MAX_UPLOAD_BYTES:
            raise RequestDataTooBig("The request is larger than the allowed upload size.")
        return None

    def receive_data_chunk(self, raw_data, start):
        return raw_data

    def file_complete(self, file_size):
        return None
