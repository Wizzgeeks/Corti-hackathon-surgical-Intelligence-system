## Server Management Rule
- NEVER run commands that start the application/dev server (e.g. `npm run dev`, `npm start`, `python manage.py runserver`, `flask run`, etc.)
- I (the user) will always start and stop the server manually.
- If you need to verify behavior, ASSUME the server may already be running and check against it (e.g. curl localhost:3000, check logs, run tests against a running instance).
- If the server is not running and you need it running to verify something, STOP and ask me to start it — do not start it yourself.