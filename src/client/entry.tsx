import * as React from "react";
import * as ReactDOM from "react-dom";
import App from "../components/App";

declare global {
    interface NodeModule {
        hot?: any;
    }
}
console.log(module.hot);
ReactDOM.render(<App />, document.getElementById("react-root"));

if (module.hot) {
    module.hot.accept("../components/App.tsx", function () {
        console.log("Accepted new module");
        
        ReactDOM.render(<App />, document.getElementById("react-root"));
    })
}
