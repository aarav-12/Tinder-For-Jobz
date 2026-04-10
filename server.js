require("dotenv").config()

const express = require("express")
const cors = require("cors")
const connectDB = require("./config/db")
const userRoutes = require("./routes/userRoutes")
const app = express()
const authRoutes = require("./routes/authRoutes")
// connect database
connectDB()
const jobRoutes = require("./routes/jobRoutes");

// middleware
app.use(cors())
app.use(express.json())
app.use("/api/jobs", jobRoutes);
app.use("/users", userRoutes)
app.use("/auth", authRoutes)
// test route
app.get("/", (req, res) => {
  res.send("API is running")
})

const PORT = process.env.PORT || 5000

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`)
})