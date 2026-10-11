"""WSGI entry point for production servers (gunicorn, uWSGI, Render, Railway).

    gunicorn -w 1 -k gthread --threads 4 wsgi:app
"""

from tera.webapp import app

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
