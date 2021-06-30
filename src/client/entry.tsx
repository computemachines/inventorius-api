import * as React from "react";
import * as ReactDOM from "react-dom";
import {
  createFrontloadState,
  FrontloadState,
  FrontloadProvider,
} from "react-frontload";
import App from "../components/App";
import { BrowserRouter } from "react-router-dom";
import { ApiContext, InventoryApi } from "../api-client/inventory-api";

declare global {
  interface Window {
    __FRONTLOAD_SERVER_STATE?: FrontloadState;
    __DEV_MODE?: boolean;
  }
  interface NodeModule {
    hot?: any;
  }
}

const ClientApp = ({ frontloadState }) => (
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
