/** Main entry for node server. */
import * as React from "react";
import { renderToString } from "react-dom/server";
import * as express from "express";
import { docopt } from "docopt";
import {
  createFrontloadState,
  FrontloadProvider,
  frontloadServerRender,
  FrontloadState,
} from "react-frontload";
import { StaticRouter } from "react-router-dom";
import * as path from "path";
import * as cors from "cors";

import * as Sentry from "@sentry/node";
import * as Tracing from "@sentry/tracing";

import App from "../components/App";
import { InventoryApi } from "../api-client/inventory-api";
const API_HOSTNAME = "http://localhost:8081";

const doc = `
Usage:
  server.bundle.js [options]

Options:
  -h --help                     Show this screen.
  --version                     Show version.
  --dev                         Tell client.ts to be dev mode. Put __DEV_MODE=true on window.
  -p <port>, --port <port>      Listen port. [default: 80]
  --noclient                    Do not send client bundle. Only perform server rendering.
`;

const args = docopt(doc, { version: "1.0.0" });
const port = parseInt(args["--port"] || 80);
const dev: boolean = args["--dev"];
const noclient: boolean = args["--noclient"];

const app = express();

Sentry.init({
  dsn: "https://841e6ad3756e472085e3e924a0ded641@o1103275.ingest.sentry.io/6150241",
  integrations: [
    // enable HTTP calls tracing
    new Sentry.Integrations.Http({ tracing: true }),
    // enable Express.js middleware tracing
    new Tracing.Integrations.Express({ app }),
  ],

  // Set tracesSampleRate to 1.0 to capture 100%
  // of transactions for performance monitoring.
  // We recommend adjusting this value in production
  tracesSampleRate: 1.0,
});

// RequestHandler creates a separate execution context using domains, so that every
// transaction/span/breadcrumb is attached to its own Hub instance
app.use(Sentry.Handlers.requestHandler());
// TracingHandler creates a trace for every incoming request
app.use(Sentry.Handlers.tracingHandler());


/**
 * Generate HTML from template.
 * @param app - The complete server-side-rendered app.
 * @param frontloadServerData - The cached data for frontload.
 * @param dev - Development flag
 * @param noclient - Disable all client side js for testing server rendering.
 * @returns The complete HTML page.
 */
function htmlTemplate(
  app: string,
  frontloadServerData,
  dev = false,
  noclient = false
) {
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
            window.__FRONTLOAD_SERVER_STATE = ${JSON.stringify(
    frontloadServerData
  ).replace(/</g, "\\u003c")}
        </script>
        ${!noclient ? '<script src="/assets/client.bundle.js"></script>' : ""}
    </body>
    </html>`;
}


// TODO: have assets served directly by nginx. issues/1
app.use(
  "/assets",
  express.static(path.join(__dirname, "assets"), { fallthrough: true })
);
app.get("/assets/*", (_, res) => res.sendStatus(404)); // fallthrough

app.get("/debug-sentry", function mainHandler(req, res) {
  throw new Error("My first Sentry error!");
});

app.get("/*", cors(), async function (req, res) {
  dev && console.log(req.path);

  
  const frontloadState = createFrontloadState.server({
    context: { api: new InventoryApi(API_HOSTNAME) },
    logging: dev,
  });

  try {
    // context contains all the attempted staticrouter state changes by <Redirect/> renders or 404s etc.
    // after rendering <StaticRouter context={context}>...</> check context object.
    const context: { url?: string; status?: number } = {};
    const { rendered, data } = await frontloadServerRender({
      frontloadState,
      render: () =>
        renderToString(
          <StaticRouter location={req.url} context={context}>
            <FrontloadProvider initialState={frontloadState}>
              <App />
            </FrontloadProvider>
          </StaticRouter>
        ),
    });

    if (context.url) {
      // somewhere in StaticRouter component tree, there was a <Redirect/> rendered
      if (context.status) res.redirect(context.status, context.url);
      else res.redirect(context.url);
    }

    const complete_page = htmlTemplate(rendered, data, dev, noclient);

    // if rendered a status code, return rendered output with that status code
    if (context.status) res.status(context.status).send(complete_page);
    // otherwise just return the rendered output with default status code (200?)
    else res.send(complete_page);
  } catch (err) {
    console.error(err);
  }
});

// The error handler must be before any other error middleware and after all controllers
app.use(Sentry.Handlers.errorHandler());

app.listen(port);
