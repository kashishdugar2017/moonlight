# moonlight
An AI explorer that finds old medicines that might help new/rare diseases

## What it does
- You enter a disease
- If you don't know what disease and only know a description it suggests a list of disease's to pick from
- It removes medicines already known for that disease, so only new clues are left
- It will link your disease -> protein -> medicine
- It will also explain it in easy to understand terms

**For research, not medical advice**

## Run in a container
```bash
docker build -t moonlight .
docker run --rm -p 8080:8080 -e GEMINI_API_KEY moonlight
```
Then open http://localhost:8080. The Gemini key is never inside the image.
`-e GEMINI_API_KEY` passes the key from your own terminal into the running
container (on Cloud Run, set it as a secret). Without a key the page still
works and explanations use the built-in template.

## The Team
- Co-founders: Me (Kashish, 9yo) and Papa (Shreshth)
- Designer: Mumma (Sidha)
- Tester: Agastya (7yo)
- Tech-Lead: Me (Kashish, 9yo)

## Built for
Startup Buildathon India 2026, Google DeepMind x Google Cloud
