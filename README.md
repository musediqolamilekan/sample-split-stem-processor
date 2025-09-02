
# 🎼 Sample Split Stem Processor

The Sample Split Stem Processor project is a robust solution for automating the separation and processing of music tracks into individual stems (such as vocals, drums, bass, etc.) and automating the uploading of each stem to designated YouTube channels based on stem type.

This system integrates with Demucs for stem separation, and YouTube API for video uploads, providing a seamless workflow for music producers and content creators.

## 🔧 Setup Instructions

### Prerequisites

- Python 3.8+ (ensure Python is added to your system PATH)
- ffmpeg: Required for audio processing (ensure it’s installed and added to your system PATH).
- ImageMagick: Required for image manipulation in video rendering.

### 1. Clone the Repository

Clone the repository to your local machine:

```bash
git clone https://github.com/musediqolamilekan/sample-split-stem-processor.git
cd sample-split-stem-processor
```

### 2. Set Up Virtual Environment

Create a Python virtual environment:

```bash
python -m venv venv
```

Activate the virtual environment:

- **Windows**:
  ```bash
  venv\Scriptsctivate
  ```
- **macOS/Linux**:
  ```bash
  source venv/bin/activate
  ```

### 3. Install Dependencies

Install the necessary dependencies listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

## ▶️ Running the FastAPI Server

The FastAPI server is the core backend that handles requests, progress tracking, and stem processing tasks. After setting up your environment, run the following command to start the server:

```bash
uvicorn tk:app --reload
```

This will start the FastAPI server locally at [http://127.0.0.1:8000](http://127.0.0.1:8000).

## ⚙️ Running the Celery Worker

The system uses Celery for asynchronous task processing (specifically for handling stem separation and uploading tasks). To start the Celery worker, run:

```bash
PYTHONPATH=$(pwd) celery -A celery_worker worker --loglevel=info
```

This ensures tasks are handled concurrently and in the background.

## 📁 Project Structure

The project is organized as follows:

- `tk.py`: Main FastAPI entry point. Handles API routes and initializes the server.
- `content_download_*`: These classes (e.g., content_download_vocal, content_download_drum) handle stem processing for each stem type (vocals, drums, sample split).
- `yt_video_multi.py`: Manages video uploads to YouTube, ensuring each stem is uploaded to the correct channel.
- `shared_state.py`: Tracks the progress of stem extraction and upload for each request.
- `yt_tokens/`: Contains the authentication tokens for YouTube uploads. Tokens must be authorized and placed in this folder for proper functioning.
- `separated/`: Directory where Demucs stores the separated stems after processing.
- `MP4/`: Final rendered video files (with thumbnails) ready for upload.

## 💡 Notes

- Demucs (GitHub Link) is used for separating the stems of the audio track. Make sure Demucs is properly installed and configured.
- **YouTube Upload**: Uploads are managed through the YouTube API. Each stem is uploaded to a specified channel using pre-configured YouTube tokens located in the `yt_tokens/` folder.
- Ensure ffmpeg and ImageMagick are correctly installed and available in your system path for video processing tasks.
- YouTube upload tokens must be authorized by the user and placed in the `yt_tokens` folder. Follow the YouTube API documentation to generate these tokens.

## Playlist Auto-Add

This project also supports automatic addition of stem videos to specified YouTube playlists (based on user selection). Make sure the correct playlist IDs are set in the configuration.

## ⚠️ Troubleshooting

- **Error with Stem Separation**: If you experience issues with stem separation, ensure that ffmpeg and ImageMagick are installed and accessible in your PATH.
- **YouTube API Errors**: Check that your API tokens are valid and placed correctly in the `yt_tokens` folder. If the upload fails, verify that the OAuth 2.0 tokens are properly authorized.

## 📝 Client Documentation

This system automates the extraction, rendering, and uploading of music stems, making it ideal for content creators who need an efficient solution for distributing stem tracks to multiple YouTube channels. The system processes audio files asynchronously, ensuring tasks like stem separation and video rendering do not block other operations. The integration with YouTube allows for seamless uploading to designated playlists and channels.

For additional help, please refer to the API documentation or reach out if you encounter issues during setup or usage.

Let us know if you face any challenges during the setup. We're here to help!

Feel free to make any adjustments as needed before adding this to your Git repository!
