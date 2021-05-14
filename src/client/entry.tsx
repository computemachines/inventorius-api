import * as React from "react";
import * as ReactDOM from "react-dom";
import { FrontloadState } from "react-frontload";
import App from "../components/App";

declare global {
    interface Window {
        __FRONTLOAD_DATA?: FrontloadState;
    }
    interface NodeModule {
        hot?: any;
    }
}

console.log("running");

if (window.__FRONTLOAD_DATA) {
    console.log("Hydrating");
    ReactDOM.hydrate(<App initialState={0} />, document.getElementById("react-root"));
} else {


    ReactDOM.render(<App initialState={0} />, document.getElementById("react-root"));

    if (module.hot) {
        module.hot.accept("../components/App.tsx", function () {
            console.log("Accepted new module");
        
            ReactDOM.render(<App initialState={0} />, document.getElementById("react-root"));
        })
    }
}