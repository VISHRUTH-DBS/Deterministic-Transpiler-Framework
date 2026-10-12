def analyze_student_performance(marks, passing_score):
    total = 0
    passed = 0
    failed = 0
    highest = marks[0]
    lowest = marks[0]
    grades = []
    student_count = len(marks)

    for mark in marks:
        total += mark

        if mark > highest:
            highest = mark

        if mark < lowest:
            lowest = mark

        if mark >= passing_score:
            passed += 1
        else:
            failed += 1

        if mark >= 90:
            grade = "A+"
        elif mark >= 80:
            grade = "A"
        elif mark >= 70:
            grade = "B"
        elif mark >= 60:
            grade = "C"
        elif mark >= passing_score:
            grade = "D"
        else:
            grade = "F"

        grades.append(grade)

    average = total / student_count
    pass_percentage = (passed / student_count) * 100

    print("Student Performance Report")
    print("--------------------------")
    print("Total Marks:", total)
    print("Average:", average)
    print("Highest:", highest)
    print("Lowest:", lowest)
    print("Passed:", passed)
    print("Failed:", failed)
    print("Pass Percentage:", pass_percentage)
    print("Grades:", grades)

    return average


student_marks = [95, 82, 76, 64, 58, 39, 91, 45]

report = analyze_student_performance(student_marks, 40)

print("Average returned:", report)