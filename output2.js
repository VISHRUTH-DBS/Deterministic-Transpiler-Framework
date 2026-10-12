function analyze_student_performance(marks, passing_score) {
  let grade;
  let total = 0;
  let passed = 0;
  let failed = 0;
  let highest = marks[0];
  let lowest = marks[0];
  let grades = [];
  let student_count = marks.length;
  for (let mark of marks) {
    total += mark;
    if (mark > highest) {
      highest = mark;
    }
    if (mark < lowest) {
      lowest = mark;
    }
    if (mark >= passing_score) {
      passed += 1;
    } else {
      failed += 1;
    }
    if (mark >= 90) {
      grade = "A+";
    } else if (mark >= 80) {
      grade = "A";
    } else if (mark >= 70) {
      grade = "B";
    } else if (mark >= 60) {
      grade = "C";
    } else if (mark >= passing_score) {
      grade = "D";
    } else {
      grade = "F";
    }
    grades.push(grade);
  }
  let average = total / student_count;
  let pass_percentage = passed / student_count * 100;
  console.log("Student Performance Report");
  console.log("--------------------------");
  console.log("Total Marks:", total);
  console.log("Average:", average);
  console.log("Highest:", highest);
  console.log("Lowest:", lowest);
  console.log("Passed:", passed);
  console.log("Failed:", failed);
  console.log("Pass Percentage:", pass_percentage);
  console.log("Grades:", grades);
  return average;
}

let student_marks = [95, 82, 76, 64, 58, 39, 91, 45];
let report = analyze_student_performance(student_marks, 40);
console.log("Average returned:", report);
