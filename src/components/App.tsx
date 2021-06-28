import "core-js/features/object";

import * as React from "react";
import { ReactNode, useState } from "react";
import { Route, Switch, Link } from "react-router-dom";

import "normalize.css";
import "../styles/accessibility.css";
import "../styles/App.css";

import { AlertContext, Alert } from "./Alert";
import ErrorBoundary from "./ErrorBoundary";
import Topbar from "./Topbar";
import Navbar from "./Navbar";
import Home from "./Home";
import NewBin from "./NewBin";
import Bin from "./Bin";
import { FourOhFour } from "./FourOhFour";
import SearchForm from "./SearchForm";
import Sku from "./Sku";
import NewSku from "./NewSku";
import EULA from "./EULA";

// test change

// second change

// third change

// fourth change

// prerelease change

function App() {
  const [alertContent, setAlertContent] = useState<{
    content?: ReactNode;
    mode?: "success" | "failure";
  }>({});
  const [dropdownIsActive, setDropdownIsActive] = useState(false);

  // const setDropdownIsActive = (state: boolean) => {
  //   console.log("setDropdownIsActive(" + state + ")");
  //   _setDropdownIsActive(state);
  // };

  return (
    <div className="app-wrapper">
      <Topbar isActive={dropdownIsActive} setActive={setDropdownIsActive} />
      <Navbar isActive={dropdownIsActive} setActive={setDropdownIsActive} />
      <div className="main-container">
        <div className="main-content" id="main">
          <ErrorBoundary>
            <AlertContext.Provider value={{ setAlertContent }}>
              <Alert
                onClose={() => setAlertContent({ content: null })}
                mode={alertContent.mode}
              >
                {alertContent.content}
              </Alert>
              <Switch>
                <Route exact path="/" component={Home} />
                <Route path="/new/bin" component={NewBin} />
                <Route path="/new/sku" component={NewSku} />
                <Route path="/bin/:id" component={Bin} />
                <Route path="/sku/:id" component={Sku} />
                <Route path="/search" component={SearchForm} />
                <Route path="/legal" component={EULA} />
                <Route component={FourOhFour} />
              </Switch>
            </AlertContext.Provider>
          </ErrorBoundary>
        </div>
        <Link to="/legal">Legal</Link>
      </div>
    </div>
  );
}

export default App;
