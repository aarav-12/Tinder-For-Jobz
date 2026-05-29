const mongoose = require("mongoose");

const userInterestSchema = new mongoose.Schema(
  {
    userId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: "User",
      required: true,
      index: true,
    },
    category: {
      type: String,
      required: true,
      index: true,
    },
    score: {
      type: Number,
      default: 0,
    },
  },
  {
    timestamps: true,
  }
);

userInterestSchema.index({ userId: 1, category: 1 }, { unique: true });

module.exports = mongoose.model("UserInterest", userInterestSchema);