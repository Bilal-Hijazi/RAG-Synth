from fastapi import FastAPI

app = FastAPI()


@app.get('/')
def hello():
    return {'return': 'hello world!!'}