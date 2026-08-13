<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="robots" content="noindex">
        <title>Server Error - {{ config('app.name', 'Fluid') }}</title>
        <link rel="icon" type="image/jpeg" href="/favicons/flux_logo.jpg">
        <style>
            :root { color-scheme: dark; }
            * { box-sizing: border-box; }
            html, body { min-height: 100%; margin: 0; }
            body {
                display: grid;
                place-items: center;
                padding: 24px;
                background: #0b0d12;
                color: #e5e7eb;
                font-family: "IBM Plex Sans", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            main { width: min(100%, 480px); text-align: center; }
            .logo {
                width: 64px;
                height: 64px;
                border: 1px solid #4b5563;
                border-radius: 14px;
                object-fit: cover;
            }
            .code { margin-top: 26px; color: #f9fafb; font-size: 34px; font-weight: 700; letter-spacing: .08em; }
            p { margin: 12px auto 0; max-width: 390px; color: #9ca3af; line-height: 1.6; }
        </style>
    </head>
    <body>
        <main>
            <img class="logo" src="/favicons/flux_logo.jpg" alt="Fluid">
            <div class="code">500</div>
            <p>The panel could not complete this request. Please try again shortly.</p>
        </main>
    </body>
</html>
