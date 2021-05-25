import * as React from "react";
import { useState } from "react";

import "../styles/NavbarDropdown.css";

function NavlinkDropdown({
  text,
  children,
}: {
  text: string;
  children: React.ReactNode;
}) {
  const [showChildren, setShowChildren] = useState(false);
  return (
    <div className="navlink navlink-dropdown screen-reader screen-reader-focusable">
      <span>{text}</span>
      <div className="nav"></div>
      {children}
    </div>
  );
}

export default NavlinkDropdown;
