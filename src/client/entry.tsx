import * as React from "react";
import * as ReactDOM from "react-dom";
// import ReactModal from "react-modal";
import {
  createFrontloadState,
  FrontloadState,
  FrontloadProvider,
} from "react-frontload";
import App from "../components/App";
import * as Sentry from "@sentry/react";
import { Integrations } from "@sentry/tracing";
import { BrowserRouter } from "react-router-dom";
import { ApiContext, InventoryApi } from "../api-client/inventory-api";


Sentry.init({
  dsn: "https://8a8c648e7a5d46a6b2bc2181f19bbcf0@o1103275.ingest.sentry.io/6129950",
  integrations: [new Integrations.BrowserTracing()],

  // We recommend adjusting this value in production, or using tracesSampler
  // for finer control
  tracesSampleRate: 1.0,
});

declare global {
  interface Window {
    __FRONTLOAD_SERVER_STATE?: FrontloadState;
    __DEV_MODE?: boolean;
  }
  interface NodeModule {
    hot?: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  }
}

const ClientApp = ({ frontloadState }: {frontloadState: FrontloadState}) => (
  <BrowserRouter>
    <FrontloadProvider initialState={frontloadState}>
      <ApiContext.Provider value={frontloadState.context.api}>
        <App />
      </ApiContext.Provider>
    </FrontloadProvider>
  </BrowserRouter>
);

if (window.__FRONTLOAD_SERVER_STATE) {
  // console.log("Frontload server hydrate branch");
  const frontloadState = createFrontloadState.client({
    context: {
      api: new InventoryApi(window.__DEV_MODE ? "http://localhost:8081" : ""),
    },
    serverRenderedData: window.__FRONTLOAD_SERVER_STATE,
    logging: window.__DEV_MODE,
  });

  ReactDOM.hydrate(
    <ClientApp frontloadState={frontloadState} />,
    document.getElementById("react-root")
  );
} else {
  console.log("Frontload client dev branch");
  // no server side rendering DEVELOPMENT ONLY
  const frontloadState = createFrontloadState.client({
    serverRenderedData: {},
    context: { api: new InventoryApi("http://localhost:8081") },
    logging: true,
  });
  frontloadState.setFirstRenderDoneOnClient();
  ReactDOM.render(
    <ClientApp frontloadState={frontloadState} />,
    document.getElementById("react-root")
  );

  if (module.hot) {
    module.hot.accept("../components/App.tsx", function () {
      console.log("Accepted new module");
      ReactDOM.render(
        <ClientApp frontloadState={frontloadState} />,
        document.getElementById("react-root")
      );
    });
  }
}
