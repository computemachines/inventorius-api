import * as React from "react";

import "../styles/NavbarDropdown.css";

const NavbarDropdown = ({
  text,
  children,
}: {
  text: string;
  children: React.ReactNode;
}) => (
  <div className="navlink navlink-dropdown">
    <span>{text}</span>
    {children}
  </div>
);

export default NavbarDropdown;
