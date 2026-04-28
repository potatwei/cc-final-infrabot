from fastapi import FastAPI
from app.api.routes.tasks import router as task_router
from app.db.database import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title="InfraPilot Backend")

app.include_router(task_router, prefix="/api")

@app.get("/")
def root():
    return {"message": "InfraPilot Backend is running"}