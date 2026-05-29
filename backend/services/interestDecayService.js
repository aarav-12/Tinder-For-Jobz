const UserInterest = require("../models/UserInterest");
const { clearCachedInterests } = require("./interestService");

const DAILY_DECAY_RATE = 0.95;

async function decayUserInterests() {
  const interests = await UserInterest.find({}).lean();

  if (interests.length === 0) {
    return { updated: 0 };
  }

  const touchedUsers = new Set();
  const operations = interests.map((interest) => {
    touchedUsers.add(String(interest.userId));

    return {
      updateOne: {
        filter: { _id: interest._id },
        update: {
          $set: {
            score: Number((interest.score * DAILY_DECAY_RATE).toFixed(2)),
          },
        },
      },
    };
  });

  if (operations.length > 0) {
    await UserInterest.bulkWrite(operations);
  }

  await Promise.all(Array.from(touchedUsers).map((userId) => clearCachedInterests(userId)));

  return {
    updated: operations.length,
  };
}

function startInterestDecayScheduler() {
  const intervalMs = 24 * 60 * 60 * 1000;

  setInterval(() => {
    decayUserInterests().catch((error) => {
      console.error("Interest decay failed:", error.message || error);
    });
  }, intervalMs);
}

module.exports = {
  decayUserInterests,
  startInterestDecayScheduler,
};