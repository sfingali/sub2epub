# Substack to EPUB Converter

This project is a Python script that converts a Substack newsletter archive into an EPUB file. The script fetches articles from a Substack publication, converts them into HTML chapters, and compiles them into an EPUB file. It uses the Substack API and requires a valid session cookie to retrieve content.

## Features
- Fetches articles from any Substack newsletter.
- Converts each article into an HTML-based chapter.
- Creates a fully formatted EPUB with metadata including author and newsletter name.
- Handles pagination to ensure all available articles are included.

## Requirements

- Python 3.8+
- SQLite3 (for storing fetched article metadata)
- Git (optional, if you're managing the repository)
  
### Python Dependencies:
You can install the necessary dependencies using `pip`:

```bash
pip install -r requirements.txt
