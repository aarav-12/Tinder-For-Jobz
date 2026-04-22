const Swipe = require("../models/Swipe");

const getUserSwipes = async (candidateId) => {
  return await Swipe.find({ candidateId }).lean();
};

module.exports = { getUserSwipes };