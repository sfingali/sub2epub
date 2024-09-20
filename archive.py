from dotenv import dotenv_values
from typing import List, Dict
import requests
import sqlite3
from contextlib import closing
from time import sleep
from random import random
from datetime import datetime
import xml2epub
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class Article:
    def __init__(
        self,
        id: int,
        slug: str,
        url: str,
        title: str = None,
        subtitle: str = None,
        authors: str = None,
        published: str = None,
        content_html: str = None,
    ):
        self.id = id
        self.slug = slug
        self.url = url
        self.title = title
        self.subtitle = subtitle
        self.authors = authors
        self.published = published
        self.content_html = content_html

    def __repr__(self):
        return f"Article(id={self.id}, title={self.title})"


def ensure_trailing_slash(url: str) -> str:
    return url if url.endswith('/') else url + '/'


def parse_article(article_data: dict) -> Article:
    return Article(
        id=article_data["id"],
        slug=article_data["slug"],
        url=article_data["canonical_url"],
        title=article_data.get("title"),
        subtitle=article_data.get("subtitle"),
        authors=", ".join(
            [author["name"] for author in article_data.get("publishedBylines", [])]
        ),
        published=article_data.get("post_date"),
    )


def get_archive(base_url: str, sid_cookie: str, limit: int = 50, offset: int = 0) -> List[dict]:
    archive_url = ensure_trailing_slash(base_url) + f"api/v1/archive?sort=new&limit={limit}&offset={offset}"
    headers = {"cookie": f"substack.sid={sid_cookie}"}
    
    response = requests.get(archive_url, headers=headers)
    
    # Check the status code
    if response.status_code != 200:
        logging.error(f"Error fetching archive: {response.status_code}, {response.text}")
        raise Exception(f"Failed to fetch archive: {response.status_code}")

    try:
        body = response.json()
        return body
    except requests.JSONDecodeError as e:
        logging.error(f"Failed to parse JSON: {response.text[:500]}")  # Log first 500 characters
        raise


def get_article_urls(base_url: str, sid_cookie: str) -> Dict[int, Article]:
    articles = {}
    limit = 50  # Number of articles per request
    offset = 0  # Starting point for fetching articles
    is_last_page = False
    
    while not is_last_page:
        archive = get_archive(base_url, sid_cookie, offset=offset, limit=limit)
        logging.info(f"Fetched {len(archive)} articles at offset {offset}")
        
        if len(archive) == 0:
            is_last_page = True  # Stop fetching if no articles are returned

        for article_data in archive:
            parsed_article = parse_article(article_data)
            if parsed_article.id not in articles:
                articles[parsed_article.id] = parsed_article
        
        offset += limit  # Move to the next batch of articles
    
    logging.info(f"Total articles retrieved: {len(articles)}")
    return articles


def get_article_contents(article_slug: str, base_url: str, sid_cookie: str) -> str:
    article_url = ensure_trailing_slash(base_url) + f"api/v1/posts/{article_slug}"
    headers = {"cookie": f"substack.sid={sid_cookie}"}
    
    response = requests.get(article_url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Error fetching article {article_slug}: {response.status_code}")
    
    try:
        body_html = response.json().get("body_html", "")
    except requests.JSONDecodeError as e:
        logging.error(f"Failed to get content for article {article_slug}: {response.text}")
        raise
    return body_html


def make_article_into_webpage(article: Article) -> str:
    # published is something like "2024-01-08T11:00:19.386Z"
    published = datetime.strptime(article.published, "%Y-%m-%dT%H:%M:%S.%fZ")
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{published.strftime("%Y-%m-%d")}: {article.title}</title>
</head>
<body>
  <article>
    <h1><a href="{article.url}">{article.title}</a></h1>
    <h2>{article.subtitle}</h2>
    <p>{article.authors} | {published.strftime("%Y-%m-%d")}</p>
    <hr>
    <div>{article.content_html}</div>
  </article>
</body>
</html>
"""


def main():
    env = dotenv_values(".env")
    articles = get_article_urls(env["SUBSTACK_BASE_URL"], env["SUBSTACK_SID_COOKIE"])
    logging.info(f"Found {len(articles)} articles on {env['SUBSTACK_BASE_URL']}")

    # create an sqlite database
    db_location = "./parentdata.sqlite3"
    with closing(sqlite3.connect(db_location)) as conn:
        with closing(conn.cursor()) as c:
            c.execute("PRAGMA journal_mode=WAL")
            conn.commit()

            # add the article schema
            c.execute(
                """CREATE TABLE IF NOT EXISTS articles (
                    id integer PRIMARY KEY NOT NULL,
                    slug text NOT NULL,
                    url text NOT NULL,
                    title text ,
                    subtitle text,
                    authors text,
                    published text,
                    content_html text
                )"""
            )
            conn.commit()

            # save basic article info into sqlite database in a transaction
            with conn:
                c.executemany(
                    """INSERT INTO articles
                    (id, slug, url, title, subtitle, authors, published)
                    VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                    [
                        (
                            article.id,
                            article.slug,
                            article.url,
                            article.title,
                            article.subtitle,
                            article.authors,
                            article.published,
                        )
                        for article in articles.values()
                    ]
                )
            
            # get full article text
            ids_of_articles_without_content = [
                res[0]
                for res in c.execute(
                    "SELECT id FROM articles WHERE content_html IS NULL"
                )
            ]
            for id in ids_of_articles_without_content:
                article = articles[id]
                try:
                    article.content_html = get_article_contents(
                        article.slug,
                        env["SUBSTACK_BASE_URL"],
                        env["SUBSTACK_SID_COOKIE"],
                    )
                    c.execute(
                        """UPDATE articles SET content_html = ? WHERE id = ?""",
                        (article.content_html, article.id),
                    )
                    conn.commit()
                    logging.info(f"Added content for article {article.url}")
                    # pause for a random amount of time to avoid rate limiting
                    sleep((random() + 0.5))

                except Exception as e:
                    logging.error(f"Failed to get content for article {article.url}: {e}")

            logging.info(
                f"Added the contents of {len(ids_of_articles_without_content)} articles to the database"
            )

            first_article_date = c.execute(
                "SELECT published FROM articles ORDER BY published ASC LIMIT 1"
            ).fetchone()[0]
            first_article_date = datetime.strptime(
                first_article_date, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).strftime("%Y-%m-%d")

            last_article_date = c.execute(
                "SELECT published FROM articles ORDER BY published DESC LIMIT 1"
            ).fetchone()[0]
            last_article_date = datetime.strptime(
                last_article_date, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).strftime("%Y-%m-%d")

            newsletter_name = env["SUBSTACK_NEWSLETTER_NAME"]
            book_title = f"{newsletter_name}: {first_article_date}–{last_article_date}"
            book = xml2epub.Epub(
                title=book_title,
                creator=env["SUBSTACK_NEWSLETTER_AUTHOR"],
                publisher=env["SUBSTACK_BASE_URL"],
            )

            for res in c.execute(
                "SELECT id, slug, url, title, subtitle, authors, published, content_html FROM articles WHERE content_html IS NOT NULL ORDER BY published ASC"
            ):
                article = Article(*res)
                webpage = make_article_into_webpage(article)
                chapter = xml2epub.create_chapter_from_string(
                    html_string=webpage, title=article.title, url=article.url
                )
                book.add_chapter(chapter)
                logging.info(f"Added article \"{article.published}: {article.title}\" to ebook")

            book.create_epub("./", book_title)
            logging.info(f"Created ebook './{book_title}.epub'")


if __name__ == "__main__":
    main()
