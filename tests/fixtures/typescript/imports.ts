import { readFile, writeFile } from "fs";
import { EventEmitter } from "events";
import * as path from "path";
import type { User } from "./types";

const filePath = path.join("/tmp", "data.txt");
readFile(filePath, "utf-8");
