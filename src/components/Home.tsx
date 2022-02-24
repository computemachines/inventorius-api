import * as React from "react";
import { useFrontload } from "react-frontload";
import { ApiContext } from "../api-client/api-client";
import ItemLabel from "./ItemLabel";


/**
 * Home page component
 * 
 * Should show general statistics, recent transactions, information of general interest.
 * 
 * @returns ReactElement
 */
function Home() {
  return <div>Home component</div>
  // const { data, frontloadMeta, setData } = useFrontload(
  //   "home-component",
  //   async function({ api }) {
  //     const status = await api.getStatus();
  //     return ({ status });
  //   }
  // );
  // const api = React.useContext(ApiContext);

  // if (frontloadMeta.pending) return <div>Loading</div>;
  // if (frontloadMeta.error) throw new Error("API Error\n"+frontloadMeta);
  
  // throw new Error("bad");

  // return (
  //   <div>
  //     <div
  //       onClick={() =>
  //         api.getStatus().then((status) =>
  //           setData(() => ({
  //             status,
  //           }))
  //         )
  //       }
  //     >
  //       Api Version: {data.status.version} <br />
  //       Api is ok: {data.status['is-up']}
  //     </div>
  //     <div>
  //       example bin: <ItemLabel label={"BIN000024"} />
  //     </div>
  //   </div>
  // );
}

export default Home;
