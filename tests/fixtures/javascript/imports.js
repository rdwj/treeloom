import { readFile, writeFile } from 'fs';
import path from 'path';
import { EventEmitter } from 'events';

function readConfig(filePath) {
    return readFile(filePath);
}
