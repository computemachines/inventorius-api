import * as React from "react";
import { Route } from "react-router-dom";

export default function Status({
  code,
  children,
}: {
  code: number;
  children: JSX.Element | JSX.Element[];
}): JSX.Element {
  return (
    <Route
      render={({ staticContext }) => {
        if (staticContext) staticContext.statusCode = code;
        return children;
      }}
    />
  );
}
