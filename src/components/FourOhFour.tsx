import * as React from "react";
import Status from "./Status";

export const FourOhFour = () => (
  <Status code={404}>
    <div>
      <h1>404 - Not found</h1>
    </div>
  </Status>
);
