import * as React from "react";
import { renderToString } from "react-dom/server";
import * as express from "express";
import { docopt } from "docopt";
import { createFrontloadState, frontloadServerRender, FrontloadState } from "react-frontload";
import { StaticRouter } from "react-router-dom";
import * as path from "path";
import * as cors from "cors";

import App from "../components/App";
import InventoryApi from "../api-client/inventory-api";
const API_HOSTNAME = "http://localhost:8081";

const doc = `
Usage:
  server.bundle.js [options]

Options:
  -h --help                     Show this screen.
  --version                     Show version.
  --dev                         Tell client.ts to be dev mode. Put __DEV_MODE=true on window.
  -p <port>, --port <port>      Listen port. [default: 80]
  --noclient                    Do not send client bundle.
`;

const args = docopt(doc, { version: "1.0.0" });
const port = parseInt(args['--port'] || 80);
const dev: boolean = args['--dev'];
const noclient: boolean = args['--noclient'];

function htmlTemplate(app: string, frontloadState: FrontloadState, dev = false, noclient = false) {
    return `<!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Inventory App</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5,user-scalable=no" />
        <link rel="stylesheet" href="/assets/main.css" />
    </head>
    <body>
        <div id="react-root">${app}</div>
        <script>
            window.__DEV_MODE = ${dev}
              // WARNING: See the following for security issues around embedding JSON in HTML:
              // http://redux.js.org/recipes/ServerRendering.html#security-considerations
              window.__FRONTLOAD_DATA = ${JSON.stringify(frontloadState).replace(/</g, "\\u003c")}
        </script>
        ${!noclient ? '<script src="/assets/client.bundle.js"></script>' : ""}
    </body>
    </html>`
}

const app = express();

app.use("/assets", express.static( path.join(__dirname, "assets" ), { fallthrough: true }));
app.get("/assets/*", (_, res) => res.sendStatus(404));

app.get("/*", cors(), async function (req, res) {
    dev && console.log(req.path);

    const frontloadState = createFrontloadState.server({
        context: { api: new InventoryApi(API_HOSTNAME) },
        logging: dev,
    });

    try {
        const context: { url?: string, status?: number } = {};
        const { rendered, data } = await frontloadServerRender({
            frontloadState,
            render: () => renderToString(<StaticRouter location={req.url} context={context}><App initialState={frontloadState} /></StaticRouter>)
        });

        if (context.url) {
            if (context.status) res.redirect(context.status, context.url);
            else res.redirect(context.url);
        }

        const complete_page = htmlTemplate(rendered, frontloadState, dev, noclient);

        if (context.status == 404) res.status(404).send(complete_page);
        else res.send(complete_page);
    } catch (err) {
        console.error(err);
    }
});

app.listen(port);