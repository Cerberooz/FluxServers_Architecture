const fs = require('fs');
const path = require('path');

const assetsDirectory = path.resolve(__dirname, '..', 'public', 'assets');

function removeBuildFiles(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const entryPath = path.join(directory, entry.name);

        if (entry.isDirectory()) {
            removeBuildFiles(entryPath);
        } else if (entry.name.endsWith('.js') || entry.name.endsWith('.map')) {
            fs.unlinkSync(entryPath);
        }
    }
}

fs.mkdirSync(assetsDirectory, { recursive: true });
removeBuildFiles(assetsDirectory);
