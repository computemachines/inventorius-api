import * as React from "react";
import { useState } from "react";

import "../styles/NavlinkDropdown.css";

function NavlinkDropdown({
  text,
  children,
}: {
  text: string;
  children: React.ReactNode;
}) {
  const [showChildren, setShowChildren] = useState(false);
  return (
    <React.Fragment>
      <button
        className="navlink"
        onClick={() => setShowChildren(!showChildren)}
        role="tree"
      >
        {text}
      </button>
      <div
        className={`navlink-dropdown screen-reader screen-reader-focusable ${
          showChildren ? "screen-reader-show" : ""
        }`}
      >
        {children}
      </div>
    </React.Fragment>
  );
}

export default NavlinkDropdown;
