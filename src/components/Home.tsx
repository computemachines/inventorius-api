import * as React from "react";
import { useFrontload } from "react-frontload";
import ItemLabel from "./ItemLabel";

function Home() {
  const { data, frontloadMeta } = useFrontload(
    "home-component",
    async ({ api }) => ({ version: await api.getVersion() })
  );
  if (frontloadMeta.pending) return <div>Loading</div>;
  if (frontloadMeta.error) return <div>API Error</div>;

  return (
    <div>
      <div>Api Version: {data.version}</div>
      <div>
        example bin: <ItemLabel label={"BIN000024"} />
      </div>
    </div>
  );
}

export default Home;
