Start the Portfolio Planner web interface.

Execute the startup script `./run_web.sh` which will:
- Check for Python 3
- Create/activate virtual environment
- Install dependencies if needed
- Start Flask server on port 5151

Once running, provide the URL: http://127.0.0.1:5151

Monitor the startup for any errors. If port 5151 is already in use, suggest using a different port with `PORT=8080 ./run_web.sh`.
