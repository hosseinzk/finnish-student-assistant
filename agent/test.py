def search_physics_book(query: str, course: str = None) -> str:
    """
    Search Finnish high school physics textbooks (FY1-FY8) for formulas, concepts, constants, and theory.
    
    This tool provides ACCURATE physics content from official Finnish textbooks to help grade student answers.
    Use this whenever you need to:
    - Verify the CORRECT FORMULA for a physics problem
    - Look up PHYSICAL CONSTANTS (G, c, R_Earth, etc.)
    - Understand the CORRECT SOLUTION METHOD
    - Get CONCEPTUAL EXPLANATIONS for "Selitä" questions
    - Check UNITS and NUMERICAL VALUES
    
    Args:
        query (str): Physics concept, formula, or topic to search for in Finnish.
                    Be specific about what you're looking for.
                    
                    GOOD examples:
                    - "gravitaatiovoima kaava" (when you need the formula F = GMm/r²)
                    - "Newtonin gravitaatiovakio arvo" (when you need G = 6.674×10⁻¹¹)
                    - "satelliitti ratanopeus" (when grading satellite speed problems)
                    - "putoamiskiihtyvyys" (when you need g = 9.81 m/s²)
                    - "ympyräliike keskihakuvoima" (for circular motion concepts)
                    
                    BAD examples:
                    - "physics" (too vague, not in Finnish)
                    - "question 1" (not a physics concept)
                    - "help" (not searchable)
        
        course (str, optional): Filter results to specific course if student's exam is from that course.
                               Valid values: "FY1", "FY2", "FY3", "FY4", "FY5", "FY6", "FY7", "FY8"
                               Default: None (search all courses)
                               
                               Use this when:
                               - Student's exam is labeled with a specific course
                               - You want course-appropriate formulas and concepts
                               - You need to avoid advanced topics from higher courses
                               
                               Example: course="FY5" for circular motion and gravity topics
    
    Returns:
        str: Formatted search results containing:
             - Relevant textbook passages (up to 8 results)
             - Formulas in LaTeX format
             - Physical constants with values
             - Conceptual explanations in Finnish
             - Source information (which textbook and relevance score)
             
             Each result is limited to ~800 characters to avoid token bloat.
             Results are ordered by relevance (most relevant first).
    
    Examples:
        # Basic search - find gravitational force formula
        >>> search_physics_book("gravitaatiovoima kaava")
        📚 Lähde 1 (relevanssi: 0.89) - FY5 OPPIKIRJATEKSTI 2021.md
        Gravitaatiovoiman suuruus on suoraan verrannollinen kappaleiden massaan...
        F = γ · (m₁m₂)/r²
        
        # Search with course filter - find satellite speed in FY5 context
        >>> search_physics_book("satelliitti nopeus", course="FY5")
        📚 Lähde 1 (relevanssi: 0.92) - FY5 OPPIKIRJATEKSTI 2021.md
        Satelliitin ratanopeus voidaan laskea...
        v = √(GM/r)
        
        # Find physical constant
        >>> search_physics_book("Newtonin gravitaatiovakio")
        📚 Lähde 1 (relevanssi: 0.95) - FY5 OPPIKIRJATEKSTI 2021.md
        γ = 6,67430 × 10⁻¹¹ Nm²/kg²
        
        # Conceptual explanation for grading "Selitä" questions
        >>> search_physics_book("tasainen ympyräliike selitys")
        📚 Lähde 1 (relevanssi: 0.87) - FY5 OPPIKIRJATEKSTI 2021.md
        Tasaisessa ympyräliikkeessä kappale liikkuu ympyrän muotoista rataa...
    
    Important Notes:
        - Results are in FINNISH (since textbooks are in Finnish)
        - Formulas use FINNISH decimal notation (comma: 3,14 not 3.14)
        - Always check the relevance score (0.0-1.0) - scores above 0.7 are usually reliable
        - If no results found, try different Finnish keywords or broader search terms
        - This tool searches textbook content, NOT exam questions
        - Use the returned formulas and constants to verify student calculations
    
    Common Use Cases in Grading:
        1. Student calculated satellite speed → Search "satelliitti ratanopeus kaava"
           → Get v = √(GM/r) to verify their approach
        
        2. Student answered "Selitä gravitaatio" → Search "gravitaatio selitys käsite"
           → Get conceptual explanation to compare against student's answer
        
        3. Student used wrong value for g → Search "putoamiskiihtyvyys arvo"
           → Get g ≈ 9.81 m/s² to verify
        
        4. Unclear if formula is correct → Search "[concept] kaava yhtälö"
           → Get the correct formula from textbook
        
        5. Need to know if answer approach is valid → Search "[topic] ratkaisu menetelmä"
           → Get solution methodology from worked examples
    """
    
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Build optional course filter
        query_filter = None
        if course:
            # Normalize course to uppercase (FY5, FY7, etc.)
            course_upper = course.upper()
            
            # Filter by filename containing the course code
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="filename",
                        match=MatchValue(value=course_upper)
                    )
                ]
            )
        
        # Search using Qdrant query method (NOT search method)
        results = qdrant.query(
            collection_name="physics_docs",
            query_text=query,
            query_filter=query_filter,
            limit=8  # Get up to 8 relevant results
        )
        
        # Handle no results
        if not results:
            course_info = f" (suodatettu kurssille: {course})" if course else ""
            return f"❌ Ei löytynyt kirjamateriaalia haulle: '{query}'{course_info}\n\nYritä:\n- Eri hakusanoja suomeksi\n- Laajempaa hakua ilman kurssisuodatinta\n- Tarkempia termejä (esim. 'kaava' tai 'vakio')"
        
        # Format results for grading agent
        content_parts = []
        for i, hit in enumerate(results, 1):
            # Extract payload data
            text = hit.payload.get("text", "")
            filename = hit.payload.get("filename", "Tuntematon lähde")
            header = hit.payload.get("header", "")
            score = hit.score
            
            # Limit text to 800 characters to avoid overwhelming context
            truncated_text = text[:800]
            if len(text) > 800:
                truncated_text += "..."
            
            # Add header if available (helps with context)
            context_info = f" - {header}" if header else ""
            
            # Format this result
            content_parts.append(
                f"📚 Lähde {i} (relevanssi: {score:.2f}) - {filename}{context_info}\n{truncated_text}"
            )
        
        # Join all results with clear separators
        separator = "\n\n" + ("─" * 80) + "\n\n"
        return separator.join(content_parts)
        
    except Exception as e:
        # Detailed error for debugging
        return f"❌ Virhe kirjamateriaalin haussa: {str(e)}\n\nKysely: '{query}'\nKurssi: {course if course else 'Ei suodatinta'}"


# ========== USAGE EXAMPLES ==========

# Example 1: Basic formula search
result = search_physics_book("gravitaatiovoima kaava")
# Returns: Formula F = γ·(m₁m₂)/r² from textbook

# Example 2: Search with course filter
result = search_physics_book("satelliitti nopeus", course="FY5")
# Returns: Only FY5 content about satellite speed

# Example 3: Find constant value
result = search_physics_book("putoamiskiihtyvyys arvo")
# Returns: g ≈ 9.81 m/s²

# Example 4: Conceptual explanation
result = search_physics_book("harmoninen värähdysliike käsite")
# Returns: Explanation of harmonic motion concept

# Example 5: Solution method
result = search_physics_book("ympyräliike ratkaisu")
# Returns: How to solve circular motion problems