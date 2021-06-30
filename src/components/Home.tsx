import * as React from "react";
import { useFrontload } from "react-frontload";
import { ApiContext } from "../api-client/inventory-api";
import ItemLabel from "./ItemLabel";

function Home() {
  const { data, frontloadMeta, setData } = useFrontload(
    "home-component",
    async ({ api }) => ({ version: await api.getVersion() })
  );
  if (frontloadMeta.pending) return <div>Loading</div>;
  if (frontloadMeta.error) return <div>API Error</div>;

  const api = React.useContext(ApiContext);
  console.log(api);

  React.useEffect(() => {
    setData((data) => ({
      version: "client clobber",
    }));
  }, []);

  return (
    <div>
      <div
        onClick={() =>
          api.getVersion().then((version) =>
            setData(() => ({
              version,
            }))
          )
        }
      >
        Api Version: {data.version}
      </div>
      <div>
        example bin: <ItemLabel label={"BIN000024"} />
      </div>
    </div>
  );
}

export default Home;
