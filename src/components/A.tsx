import * as React from "react";
import { useState } from "react";

import "../styles/A.css"

export default ({header}) => {
    const [count, setCount] = useState(1);
    console.log(count);
    return <div>
        <h1>{header}</h1>
        <ul>
            {new Array(count).fill(0).map((_, i) => <li key={i}>Iteasdm {i}</li>)}
        </ul>
        <button onClick={()=>setCount(count + 1)}>Add Item</button>
    </div>;
};