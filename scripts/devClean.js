const { execSync } = require("child_process");

const PORT = 5000;

function getPidsOnPort(port) {
  try {
    const output = execSync(`netstat -ano | findstr :${port}`, {
      stdio: ["ignore", "pipe", "ignore"],
      encoding: "utf8",
    });

    const pids = output
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .filter((line) => /LISTENING/i.test(line))
      .map((line) => line.split(/\s+/).pop())
      .filter(Boolean);

    return [...new Set(pids)];
  } catch {
    return [];
  }
}

function killPid(pid) {
  try {
    execSync(`taskkill /PID ${pid} /F`, { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

const pids = getPidsOnPort(PORT);

if (pids.length === 0) {
  console.log(`No process is listening on port ${PORT}.`);
  process.exit(0);
}

const killed = pids.filter(killPid);

if (killed.length > 0) {
  console.log(`Killed process(es) on port ${PORT}: ${killed.join(", ")}`);
}

const failed = pids.filter((pid) => !killed.includes(pid));
if (failed.length > 0) {
  console.error(`Failed to kill process(es): ${failed.join(", ")}`);
  process.exit(1);
}
