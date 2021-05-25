import * as React from "react";
import { useFrontload } from "react-frontload";

function Home() {
  const { data, frontloadMeta } = useFrontload(
    "home-component",
    async ({ api }) => ({ version: await api.getVersion() })
  );
  if (frontloadMeta.pending) return <div>Loading</div>;
  if (frontloadMeta.error) return <div>API Error</div>;

  return <div>Api Version: {data.version}</div>;
}

export default Home;
