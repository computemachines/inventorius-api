import * as React from "react";
import { useState } from "react";
import { FrontloadState } from "react-frontload";

import A from "./A";
import B from "./B";

export default () => {
    return (
        <div>
            <A header="headersdsdsd 1st"></A>
            <B header="headsdasdfer B"></B>
        </div>
    )
};