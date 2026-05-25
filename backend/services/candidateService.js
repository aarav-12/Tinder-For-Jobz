// const Job = require("../models/job");

// const getCandidates = async ({ user, swipes, cursor }) => {
//   const query = {
//     isActive: true,
//     _id: { $nin: swipes },
//     minExperience: { $lte: user.experience },
//   };

//   if (cursor) {
//     query.createdAt = { $lt: new Date(cursor) };
//   }

//   return Job.find(query)
//     .sort({ createdAt: -1 })
//     .limit(200)
//     .lean();
// };

// async function fetchCandidates(swipedJobIds, candidate) {
//   return getCandidates({ user: candidate, swipes: swipedJobIds, cursor: undefined });
// }

// module.exports = {
//   getCandidates,
//   fetchCandidates,
// };

const Job = require("../models/Job");

const getCandidates = async ({ user, swipes, cursor }) => {
  const query = {
    isActive: true,
    minExperience: { $lte: user.experience ?? 10 }
  };

  if (swipes && swipes.length > 0) {
    query._id = { $nin: swipes };
  }

  if (cursor) {
    query.createdAt = { $lt: new Date(cursor) };
  }

  return Job.find(query).lean()
    .sort({ createdAt: -1 })
    .limit(200);
};

module.exports = {
  getCandidates
};