import re
import frappe
from frappe.utils import flt, cint, cstr
from school.lms.md import markdown_to_html
import string

RE_SLUG_NOTALLOWED = re.compile("[^a-z0-9]+")

def slugify(title, used_slugs=[]):
    """Converts title to a slug.

    If a list of used slugs is specified, it will make sure the generated slug
    is not one of them.

        >>> slugify("Hello World!")
        'hello-world'
        >>> slugify("Hello World!", ['hello-world'])
        'hello-world-2'
        >>> slugify("Hello World!", ['hello-world', 'hello-world-2'])
        'hello-world-3'
    """
    slug = RE_SLUG_NOTALLOWED.sub('-', title.lower()).strip('-')
    used_slugs = set(used_slugs)

    if slug not in used_slugs:
        return slug

    count = 2
    while True:
        new_slug = f"{slug}-{count}"
        if new_slug not in used_slugs:
            return new_slug
        count = count+1

def get_membership(course, member, batch=None):
    filters = {
        "member": member,
        "course": course
    }
    if batch:
        filters["batch"] = batch

    membership = frappe.db.get_value("LMS Batch Membership",
        filters,
        ["name", "batch", "current_lesson", "member_type", "progress"],
        as_dict=True)

    if membership and membership.batch:
        membership.batch_title = frappe.db.get_value("LMS Batch", membership.batch, "title")
    return membership

def get_chapters(course):
    """Returns all chapters of this course.
    """
    chapters = frappe.get_all("Chapter Reference", {"parent": course},
        ["idx", "chapter"], order_by="idx")
    for chapter in chapters:
        chapter_details = frappe.db.get_value("Course Chapter", { "name": chapter.chapter },
            ["name", "title", "description"], as_dict=True)
        chapter.update(chapter_details)
    return chapters

def get_lessons(course, chapter=None):
    """ If chapter is passed, returns lessons of only that chapter.
    Else returns lessons of all chapters of the course """
    lessons = []
    if chapter:
        return get_lesson_details(chapter)

    for chapter in get_chapters(course):
        lesson = get_lesson_details(chapter)
        lessons += lesson

    return lessons

def get_lesson_details(chapter):
    lessons = []
    lesson_list = frappe.get_all("Lesson Reference",
        {"parent": chapter.name},
        ["lesson", "idx"],
        order_by="idx")

    for row in lesson_list:
        lesson_details = frappe.db.get_value("Course Lesson", row.lesson,
            ["name", "title", "include_in_preview", "body", "creation"], as_dict=True)
        lesson_details.number = flt("{}.{}".format(chapter.idx, row.idx))
        lessons.append(lesson_details)
    return lessons

def get_tags(course):
    tags = frappe.db.get_value("LMS Course", course, "tags")
    return tags.split(",") if tags else []

def get_instructors(course):
    instructor_details = []
    instructors = frappe.get_all("Course Instructor", {"parent": course},
        ["instructor"], order_by="idx")
    if not instructors:
        instructors = frappe.db.get_value("LMS Course", course, "owner").split(" ")
    for instructor in instructors:
        instructor_details.append(frappe.db.get_value("User",
            instructor.instructor,
            ["name", "username", "full_name", "user_image"],
            as_dict=True))
    return instructor_details

def get_students(course, batch=None):
    """Returns (email, full_name, username) of all the students of this batch as a list of dict.
    """
    filters = {
        "course": course,
        "member_type": "Student"
    }
    if batch:
        filters["batch"] = batch
    return frappe.get_all(
        "LMS Batch Membership",
        filters,
        ["member"])

def get_average_rating(course):
    ratings = [review.rating for review in get_reviews(course)]
    if not len(ratings):
        return None
    return sum(ratings)/len(ratings)

def get_reviews(course):
    reviews = frappe.get_all("LMS Course Review",
                {
                    "course": course
                },
                ["review", "rating", "owner", "creation"],
                order_by= "creation desc")
    out_of_ratings = frappe.db.get_all("DocField",
        {
            "parent": "LMS Course Review",
            "fieldtype": "Rating"
        },
        ["options"])
    out_of_ratings = (len(out_of_ratings) and out_of_ratings[0].options) or 5
    for review in reviews:
        review.rating = review.rating * out_of_ratings
        review.owner_details = frappe.db.get_value("User",
            review.owner, ["name", "username", "full_name", "user_image"], as_dict=True)

    return reviews

def get_sorted_reviews(course):
    rating_count = rating_percent = frappe._dict()
    keys = ["5.0", "4.0", "3.0", "2.0", "1.0"]
    for key in keys:
        rating_count[key] = 0

    reviews = get_reviews(course)
    for review in reviews:
        rating_count[cstr(review.rating)] += 1

    for key in keys:
        rating_percent[key] = (rating_count[key]/len(reviews) * 100)


    return rating_percent

def is_certified(course):
    certificate = frappe.get_all("LMS Certification",
                    {
                        "student": frappe.session.user,
                        "course": course
                    })
    if len(certificate):
        return certificate[0].name
    return

def get_lesson_index(lesson_name):
    """Returns the {chapter_index}.{lesson_index} for the lesson.
    """
    lesson = frappe.db.get_value("Lesson Reference",
        {"lesson": lesson_name}, ["idx", "parent"], as_dict=True)
    if not lesson:
        return None

    chapter = frappe.db.get_value("Chapter Reference",
        {"chapter": lesson.parent}, ["idx"], as_dict=True)
    if not chapter:
        return None

    return f"{chapter.idx}.{lesson.idx}"

def get_lesson_url(course, lesson_number):
    if not lesson_number:
        return
    return f"/courses/{course}/learn/{lesson_number}"

def get_batch(course, batch_name):
    return frappe.get_all("LMS Batch", {"name": batch_name, "course": course})

def get_slugified_chapter_title(chapter):
    return slugify(chapter)

def get_progress(course, lesson):
    return frappe.db.get_value("LMS Course Progress", {
            "course": course,
            "owner": frappe.session.user,
            "lesson": lesson
        },
        ["status"])

def render_html(body):
    return markdown_to_html(body)

def is_mentor(course, email):
    """Checks if given user is a mentor for this course.
    """
    if not email:
        return False
    return frappe.db.count("LMS Course Mentor Mapping",
        {
            "course": course,
            "mentor": email
        })

def is_cohort_staff(course, user_email):
    """Returns True if the user is either a mentor or a staff for one or more active cohorts of this course.
    """
    staff = {
        "doctype": "Cohort Staff",
        "course": course,
        "email": user_email
    }
    mentor = {
        "doctype": "Cohort Mentor",
        "course": course,
        "email": user_email
    }
    return frappe.db.exists(staff) or frappe.db.exists(mentor)

def get_mentors(course):
    """Returns the list of all mentors for this course.
    """
    course_mentors = []
    mentors = frappe.get_all("LMS Course Mentor Mapping", {"course": course}, ["mentor"])
    for mentor in mentors:
        member = frappe.db.get_value("User", mentor.mentor,
            ["name", "username", "full_name", "user_image"])
        member.batch_count = frappe.db.count("LMS Batch Membership",
                                {
                                    "member": member.name,
                                    "member_type": "Mentor"
                                })
        course_mentors.append(member)
    return course_mentors

def is_eligible_to_review(course, membership):
    """ Checks if user is eligible to review the course """
    if not membership:
        return False
    if frappe.db.count("LMS Course Review",
            {
                "course": course,
                "owner": frappe.session.user
            }):
        return False
    return True

def get_course_progress(course, member=None):
    """ Returns the course progress of the session user """
    lesson_count = len(get_lessons(course))
    if not lesson_count:
        return 0
    completed_lessons = frappe.db.count("LMS Course Progress",
                            {
                                "course": course,
                                "owner": member or frappe.session.user,
                                "status": "Complete"
                            })
    precision = cint(frappe.db.get_default("float_precision")) or 3
    return flt(((completed_lessons/lesson_count) * 100), precision)

def get_initial_members(course):
    members = frappe.get_all("LMS Batch Membership",
        {
            "course": course
        },
        ["member"],
        limit=3)

    member_details = []
    for member in members:
        member_details.append(frappe.db.get_value("User",
            member.member, ["name", "username", "full_name", "user_image"], as_dict=True))

    return member_details

def is_instructor(course):
    return len(list(filter(lambda x: x.name == frappe.session.user, get_instructors(course)))) > 0

def convert_number_to_character(number):
    return string.ascii_uppercase[number]
