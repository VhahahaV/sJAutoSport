"""Start the Web API; run the Vite frontend in a separate terminal."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("web_api.app:app", host="127.0.0.1", port=8000)
